// Shared by the full editor and Light. Overlay alpha is the editable selection.
window.JoyBoyMask = {
    dot(ctx, x, y, radius, erase = false) {
        ctx.globalCompositeOperation = erase ? 'destination-out' : 'source-over';
        ctx.fillStyle = 'white';
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fill();
    },
    export(canvas) {
        const output = document.createElement('canvas');
        output.width = canvas.width;
        output.height = canvas.height;
        const ctx = output.getContext('2d');
        const source = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
        const mask = ctx.createImageData(canvas.width, canvas.height);
        for (let i = 0; i < source.data.length; i += 4) {
            mask.data[i] = mask.data[i + 1] = mask.data[i + 2] = source.data[i + 3];
            mask.data[i + 3] = 255;
        }
        ctx.putImageData(mask, 0, 0);
        return output.toDataURL('image/png');
    },
};
